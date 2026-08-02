// SPDX-License-Identifier: GPL-3.0
/*
    Copyright 2021 0KIMS association.

    This file is generated with [snarkJS](https://github.com/iden3/snarkjs).

    snarkJS is a free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    snarkJS is distributed in the hope that it will be useful, but WITHOUT
    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
    or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
    License for more details.

    You should have received a copy of the GNU General Public License
    along with snarkJS. If not, see <https://www.gnu.org/licenses/>.
*/

pragma solidity >=0.7.0 <0.9.0;

contract VCPGroth16Verifier {
    // Scalar field size
    uint256 constant r    = 21888242871839275222246405745257275088548364400416034343698204186575808495617;
    // Base field size
    uint256 constant q   = 21888242871839275222246405745257275088696311157297823662689037894645226208583;

    // Verification Key data
    uint256 constant alphax  = 8690092375852571756268708963344981089057913201761232177527809372579775195830;
    uint256 constant alphay  = 13188635787717563532534574189496546905977508318230903823902000402965018451073;
    uint256 constant betax1  = 21131298365984457075336238462152080984068598055661674148407620437507140788778;
    uint256 constant betax2  = 18137487431491403576751548791968060032854016199109524760675492819181105385447;
    uint256 constant betay1  = 20121414048117460008196568925144725746391584713137916682212991935247772881845;
    uint256 constant betay2  = 6553142021885523541878348825388191704319788522422174270859963189488004232704;
    uint256 constant gammax1 = 11559732032986387107991004021392285783925812861821192530917403151452391805634;
    uint256 constant gammax2 = 10857046999023057135944570762232829481370756359578518086990519993285655852781;
    uint256 constant gammay1 = 4082367875863433681332203403145435568316851327593401208105741076214120093531;
    uint256 constant gammay2 = 8495653923123431417604973247489272438418190587263600148770280649306958101930;
    uint256 constant deltax1 = 359593999436480266015597888211997401497972565412315067160387743314557934246;
    uint256 constant deltax2 = 11602736238999564983785630768856820450178170282498726938968717398619451833282;
    uint256 constant deltay1 = 19174592390817977409442466294924740246898465508752232909492240334127660210845;
    uint256 constant deltay2 = 2719240972326678454888625154078118021998041967060250614283256623022708213511;

    
    uint256 constant IC0x = 19058251930559443240388286981678341088922358646917794643122778416894434002046;
    uint256 constant IC0y = 12806624046648996579118247296564364244981273387911116976298012681825342010074;
    
    uint256 constant IC1x = 3190020931245906033936132416096305021607978052273119872220649162972316470770;
    uint256 constant IC1y = 11781681288449992378550992862726094466546570253913745648279510427578567243258;
    
    uint256 constant IC2x = 10337312047026444754012157012953630276926480369192517787854574432686963325739;
    uint256 constant IC2y = 14099324150248308106604552208323413895716019613332762965284997809079953623535;
    
    uint256 constant IC3x = 5495615301801741562473899641854340190594951125012341681384992399097494421442;
    uint256 constant IC3y = 6390408688293635322780033018707334307835085468650990015201196043834777281539;
    
    uint256 constant IC4x = 4200773115281953451685405311425355124378125695404127907316891633518031661141;
    uint256 constant IC4y = 12051897873481932882068896740234225834185526588343612429916172774598695957710;
    
    uint256 constant IC5x = 1457149201097494561324817451513281122176089721025022071022696569426838986122;
    uint256 constant IC5y = 15109219426695846042695661201081821711937014386720846726279073744739631085733;
    
    uint256 constant IC6x = 16225314183562646335716020360263486277271440596952840138776437887374989044819;
    uint256 constant IC6y = 9750798318428202605228804710120135919895345591217736749352058768538317820209;
    
    uint256 constant IC7x = 7680371068809030932793616222560492875524079822112064798504751180157910581757;
    uint256 constant IC7y = 10277069141494363505751080742290311143367169820860236334982368522928846298106;
    
    uint256 constant IC8x = 4093470849310916549752692776959032346467325214696133976357758077917152557312;
    uint256 constant IC8y = 11060259070035782224997273885889425581740728039051812298368479476409406910023;
    
    uint256 constant IC9x = 9953521802245304231658086430355895041698788367616985492085068665828846977077;
    uint256 constant IC9y = 16110438038884077706366031766533060918769633820518081342917278646440885843594;
    
    uint256 constant IC10x = 10095127348475243400145359906774368376009480008804040378058048357119962743256;
    uint256 constant IC10y = 19996836769687359705715255791118412295436834340884033774029724937740764743109;
    
    uint256 constant IC11x = 10733521221245570869783684291878962362801518378001526718980658338999023733590;
    uint256 constant IC11y = 15189318702919062179419776521458508839713605076596955895779793777378770551172;
    
    uint256 constant IC12x = 16897382716098700519897813417480800609681224217559327457493581776413044283746;
    uint256 constant IC12y = 2955566085440627008938553010847001619421999486331969427975964521553875641872;
    
    uint256 constant IC13x = 18939064925479440027158017080687076638230737081010017725424359707589940800912;
    uint256 constant IC13y = 20004476269549517030120077110003078259774088179169025299907965775130219070882;
    
    uint256 constant IC14x = 10689330789299357754713655284920133658368741772227178922377073493645969145540;
    uint256 constant IC14y = 9124358063319869583979184144790536081870237497604825393039324133549882228217;
    
    uint256 constant IC15x = 20447251015046820172799462154356190773462927802956804614790469355924923599574;
    uint256 constant IC15y = 3845369061002100999014831752329871558576861580891476409159363286775486051856;
    
    uint256 constant IC16x = 20775605592727466478496685096134984189769279186106411456522948529984665278176;
    uint256 constant IC16y = 14054175402297968293887347446583302498944095418252394851204185155806258045718;
    
    uint256 constant IC17x = 17167955221313867168032062947137923165013212456345988140944775244131160888163;
    uint256 constant IC17y = 20950620232065910520781570738222462598635701936995366486381485365558257631047;
    
    uint256 constant IC18x = 17519067662634660207638098857633006338391993570682323925453198968771493261811;
    uint256 constant IC18y = 12492546765209375782953422945781881702508758659661635469449383591961011031947;
    
    uint256 constant IC19x = 11814248391892197711581785797097451267979189840293361722000793928738414944849;
    uint256 constant IC19y = 10820976767412079097690545081628355554008268375891766810673391956681705865106;
    
    uint256 constant IC20x = 6181273241714760320994580461404674990194406298043208369195901615569433384381;
    uint256 constant IC20y = 11364786471525360208761114759733124445212039231393905243593895462281913810154;
    
    uint256 constant IC21x = 13060674652884751803348128037372688667616430706216635263554843071419224517494;
    uint256 constant IC21y = 19546350630966018589754435438058694675684213815722313959438681771130297371384;
    
    uint256 constant IC22x = 11384823700599685672483655902703772803972609032882775290641562929636610147953;
    uint256 constant IC22y = 20318075691956347617226180005740699495510280720725475915956019364278087601215;
    
    uint256 constant IC23x = 11760577488751403223035747295386790455176861158370026913509456603657571210854;
    uint256 constant IC23y = 10395867853619569059268040936185542670090334981263929913142248353157395771663;
    
    uint256 constant IC24x = 11718246359334063727521504399696143342313479425542024381972340269350657510961;
    uint256 constant IC24y = 19569195354420200863692670692244448884139305917965738267667728697839288578368;
    
 
    // Memory data
    uint16 constant pVk = 0;
    uint16 constant pPairing = 128;

    uint16 constant pLastMem = 896;

    function verifyProof(uint[2] calldata _pA, uint[2][2] calldata _pB, uint[2] calldata _pC, uint[24] calldata _pubSignals) public view returns (bool) {
        assembly {
            function checkField(v) {
                if iszero(lt(v, r)) {
                    mstore(0, 0)
                    return(0, 0x20)
                }
            }
            
            // G1 function to multiply a G1 value(x,y) to value in an address
            function g1_mulAccC(pR, x, y, s) {
                let success
                let mIn := mload(0x40)
                mstore(mIn, x)
                mstore(add(mIn, 32), y)
                mstore(add(mIn, 64), s)

                success := staticcall(sub(gas(), 2000), 7, mIn, 96, mIn, 64)

                if iszero(success) {
                    mstore(0, 0)
                    return(0, 0x20)
                }

                mstore(add(mIn, 64), mload(pR))
                mstore(add(mIn, 96), mload(add(pR, 32)))

                success := staticcall(sub(gas(), 2000), 6, mIn, 128, pR, 64)

                if iszero(success) {
                    mstore(0, 0)
                    return(0, 0x20)
                }
            }

            function checkPairing(pA, pB, pC, pubSignals, pMem) -> isOk {
                let _pPairing := add(pMem, pPairing)
                let _pVk := add(pMem, pVk)

                mstore(_pVk, IC0x)
                mstore(add(_pVk, 32), IC0y)

                // Compute the linear combination vk_x
                
                g1_mulAccC(_pVk, IC1x, IC1y, calldataload(add(pubSignals, 0)))
                
                g1_mulAccC(_pVk, IC2x, IC2y, calldataload(add(pubSignals, 32)))
                
                g1_mulAccC(_pVk, IC3x, IC3y, calldataload(add(pubSignals, 64)))
                
                g1_mulAccC(_pVk, IC4x, IC4y, calldataload(add(pubSignals, 96)))
                
                g1_mulAccC(_pVk, IC5x, IC5y, calldataload(add(pubSignals, 128)))
                
                g1_mulAccC(_pVk, IC6x, IC6y, calldataload(add(pubSignals, 160)))
                
                g1_mulAccC(_pVk, IC7x, IC7y, calldataload(add(pubSignals, 192)))
                
                g1_mulAccC(_pVk, IC8x, IC8y, calldataload(add(pubSignals, 224)))
                
                g1_mulAccC(_pVk, IC9x, IC9y, calldataload(add(pubSignals, 256)))
                
                g1_mulAccC(_pVk, IC10x, IC10y, calldataload(add(pubSignals, 288)))
                
                g1_mulAccC(_pVk, IC11x, IC11y, calldataload(add(pubSignals, 320)))
                
                g1_mulAccC(_pVk, IC12x, IC12y, calldataload(add(pubSignals, 352)))
                
                g1_mulAccC(_pVk, IC13x, IC13y, calldataload(add(pubSignals, 384)))
                
                g1_mulAccC(_pVk, IC14x, IC14y, calldataload(add(pubSignals, 416)))
                
                g1_mulAccC(_pVk, IC15x, IC15y, calldataload(add(pubSignals, 448)))
                
                g1_mulAccC(_pVk, IC16x, IC16y, calldataload(add(pubSignals, 480)))
                
                g1_mulAccC(_pVk, IC17x, IC17y, calldataload(add(pubSignals, 512)))
                
                g1_mulAccC(_pVk, IC18x, IC18y, calldataload(add(pubSignals, 544)))
                
                g1_mulAccC(_pVk, IC19x, IC19y, calldataload(add(pubSignals, 576)))
                
                g1_mulAccC(_pVk, IC20x, IC20y, calldataload(add(pubSignals, 608)))
                
                g1_mulAccC(_pVk, IC21x, IC21y, calldataload(add(pubSignals, 640)))
                
                g1_mulAccC(_pVk, IC22x, IC22y, calldataload(add(pubSignals, 672)))
                
                g1_mulAccC(_pVk, IC23x, IC23y, calldataload(add(pubSignals, 704)))
                
                g1_mulAccC(_pVk, IC24x, IC24y, calldataload(add(pubSignals, 736)))
                

                // -A
                mstore(_pPairing, calldataload(pA))
                mstore(add(_pPairing, 32), mod(sub(q, calldataload(add(pA, 32))), q))

                // B
                mstore(add(_pPairing, 64), calldataload(pB))
                mstore(add(_pPairing, 96), calldataload(add(pB, 32)))
                mstore(add(_pPairing, 128), calldataload(add(pB, 64)))
                mstore(add(_pPairing, 160), calldataload(add(pB, 96)))

                // alpha1
                mstore(add(_pPairing, 192), alphax)
                mstore(add(_pPairing, 224), alphay)

                // beta2
                mstore(add(_pPairing, 256), betax1)
                mstore(add(_pPairing, 288), betax2)
                mstore(add(_pPairing, 320), betay1)
                mstore(add(_pPairing, 352), betay2)

                // vk_x
                mstore(add(_pPairing, 384), mload(add(pMem, pVk)))
                mstore(add(_pPairing, 416), mload(add(pMem, add(pVk, 32))))


                // gamma2
                mstore(add(_pPairing, 448), gammax1)
                mstore(add(_pPairing, 480), gammax2)
                mstore(add(_pPairing, 512), gammay1)
                mstore(add(_pPairing, 544), gammay2)

                // C
                mstore(add(_pPairing, 576), calldataload(pC))
                mstore(add(_pPairing, 608), calldataload(add(pC, 32)))

                // delta2
                mstore(add(_pPairing, 640), deltax1)
                mstore(add(_pPairing, 672), deltax2)
                mstore(add(_pPairing, 704), deltay1)
                mstore(add(_pPairing, 736), deltay2)


                let success := staticcall(sub(gas(), 2000), 8, _pPairing, 768, _pPairing, 0x20)

                isOk := and(success, mload(_pPairing))
            }

            let pMem := mload(0x40)
            mstore(0x40, add(pMem, pLastMem))

            // Validate that all evaluations ∈ F
            
            checkField(calldataload(add(_pubSignals, 0)))
            
            checkField(calldataload(add(_pubSignals, 32)))
            
            checkField(calldataload(add(_pubSignals, 64)))
            
            checkField(calldataload(add(_pubSignals, 96)))
            
            checkField(calldataload(add(_pubSignals, 128)))
            
            checkField(calldataload(add(_pubSignals, 160)))
            
            checkField(calldataload(add(_pubSignals, 192)))
            
            checkField(calldataload(add(_pubSignals, 224)))
            
            checkField(calldataload(add(_pubSignals, 256)))
            
            checkField(calldataload(add(_pubSignals, 288)))
            
            checkField(calldataload(add(_pubSignals, 320)))
            
            checkField(calldataload(add(_pubSignals, 352)))
            
            checkField(calldataload(add(_pubSignals, 384)))
            
            checkField(calldataload(add(_pubSignals, 416)))
            
            checkField(calldataload(add(_pubSignals, 448)))
            
            checkField(calldataload(add(_pubSignals, 480)))
            
            checkField(calldataload(add(_pubSignals, 512)))
            
            checkField(calldataload(add(_pubSignals, 544)))
            
            checkField(calldataload(add(_pubSignals, 576)))
            
            checkField(calldataload(add(_pubSignals, 608)))
            
            checkField(calldataload(add(_pubSignals, 640)))
            
            checkField(calldataload(add(_pubSignals, 672)))
            
            checkField(calldataload(add(_pubSignals, 704)))
            
            checkField(calldataload(add(_pubSignals, 736)))
            

            // Validate all evaluations
            let isValid := checkPairing(_pA, _pB, _pC, _pubSignals, pMem)

            mstore(0, isValid)
             return(0, 0x20)
         }
     }
 }
